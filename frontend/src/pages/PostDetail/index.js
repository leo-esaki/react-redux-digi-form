import React, { PureComponent } from 'react'
import ImmutablePropTypes from 'react-immutable-proptypes'
import moment from 'moment'
import PropTypes from 'prop-types'
import { Alert, Col, Row } from 'reactstrap'
import { compose } from 'redux'
import { connect } from 'react-redux'
import { createStructuredSelector } from 'reselect'
import { Link } from 'react-router-dom'
import { show } from 'redux-modal'

import CommentForm from 'components/CommentForm'
import FrontContainerLayout from 'layouts/FrontContainerLayout'
import PostItem from 'components/PostItem'
import Section from 'components/Section'
import SectionTitle from 'components/SectionTitle'
import Spinner from 'components/Spinner'
import { API_PENDING, API_SUCCESS, API_FAIL } from 'store/api/request'
import { authSelector, blogSelector } from 'store/selectors'
import { createPostComment, getPostCommentList, getPostDetail } from 'store/modules/blog'


class PostDetail extends PureComponent {

  static propTypes = {
    auth: ImmutablePropTypes.map.isRequired,
    blog: ImmutablePropTypes.map.isRequired,
    createPostComment: PropTypes.func.isRequired,
    getPostCommentList: PropTypes.func.isRequired,
    getPostDetail: PropTypes.func.isRequired
  }

  breadcrumbPath() {
    const postDetail = this.props.blog.get('postDetail')

    return [
      { route: '/', text: 'Home' },
      { route: '/blog', text: 'Posts' },
      { text: postDetail ? postDetail.get('title') : '' },
    ]
  }

  getDetail = (id) => {
    const { getPostDetail, getPostCommentList } = this.props
    getPostDetail({ id })
    getPostCommentList({ id })
  }

  componentWillMount() {
    this.getDetail(this.props.match.params.id)
  }

  componentWillReceiveProps(nextProps) {
    if (this.props.match.params.id !== nextProps.match.params.id) {
      this.getDetail(nextProps.match.params.id)
    }
  }

  handlePostComment = (data) => {
    const { createPostComment, match: { params: { id } } } = this.props
    createPostComment({ id, data })
  }

  handleSignIn = (e) => {
    const { show } = this.props
    e.preventDefault()
    show('signinModal')
  }

  renderDetail() {
    const { auth, blog } = this.props
    const postDetail = blog.get('postDetail')
    const comments = blog.get('commentList').toJS()
    const similarPosts = postDetail.get('similar_posts')
    const post = postDetail.toJS()
    const user = auth.get('currentUser')

    return (
      <div className="page-content">
        <Section title={post.title}>
          <p><img src={post.featured_image} alt={post.title} className="w-100"/></p>
          <div className="my-5" dangerouslySetInnerHTML={{ __html: post.content }} />
        </Section>

        <Section title={`Comments (${comments ? comments.length : 0})`}>
          {comments && !!comments.length && comments.map((comment, index) => (
            <div className="mb-4" key={index}>
              <div className="mb-3">{comment.content}</div>
              <Row>
                <Col xs={6} className="mb-2">{moment(comment.created_at).format('ll')}</Col>
                <Col xs={6} className="text-right mb-2">{comment.user.full_name}</Col>
              </Row>
            </div>
          ))}
          {user
            ? <CommentForm onSubmit={this.handlePostComment} user={user} />
            : <Alert color="dark">
              Please <Link to="/signin" className="alert-link" onClick={this.handleSignIn}>sign in</Link> to leave comment
            </Alert>
          }
        </Section>

        <Section title="Similar Posts">
          <Row className="mb-5">
            {similarPosts.map(post => (
              <PostItem key={post.pk} post={post} />
            ))}
          </Row>
        </Section>
      </div>
    )
  }

  render() {
    const { blog } = this.props
    const postDetailStatus = blog.get('postDetailStatus')

    return (
      <FrontContainerLayout breadcrumbPath={this.breadcrumbPath()} subscribe>
        {postDetailStatus === API_PENDING && <Spinner />}

        {postDetailStatus === API_FAIL && <SectionTitle><center>Post not found</center></SectionTitle>}

        {postDetailStatus === API_SUCCESS && this.renderDetail()}
      </FrontContainerLayout>
    )
  }
}

const selector = createStructuredSelector({
  auth: authSelector,
  blog: blogSelector,
})

const actions = {
  createPostComment,
  getPostDetail,
  getPostCommentList,
  show
}

export default compose(
  connect(selector, actions)
)(PostDetail)
